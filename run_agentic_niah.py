"""Agentic needle-in-a-haystack: context-rot curve for agent trajectories.

Four conditions per trajectory length, over the same 12-question set:

  RAW      full session transcript in context (long-context stuffing)
  COMPACT  one question-agnostic LLM summary of the transcript
           (models today's auto-compaction), answers come from the summary
  BM25     top episodes by BM25 against the question (~3.5K BPE budget)
  CTX      steps -> IR -> entity resolution -> compress -> section index
           -> LLM routes -> hydrate_by_name -> answer  (progressive hydration)

Metrics: judge fidelity (cross-model), rule fidelity, input BPE per query.

Usage:
  python run_agentic_niah.py             # full run: 8K / 32K / 64K BPE
  python run_agentic_niah.py --smoke     # 1 length, 3 questions, plumbing check
"""

import json
import math
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()
# Force answerer to Claude so the judge auto-selects GPT-4o (cross-model)
os.environ["CTXPACK_EVAL_PROVIDER"] = "anthropic"
os.environ["CTXPACK_EVAL_MODEL"] = "claude-sonnet-4-6"

from ctxpack.agent.state_parser import parse_steps
from ctxpack.benchmarks.agentic.trajectory_gen import generate_trajectory
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
from ctxpack.benchmarks.metrics.fidelity import (
    _ask_llm, _detect_provider, _grade_answer, _llm_judge,
    _resolve_judge_params, _INTER_CALL_DELAY,
)
from ctxpack.core.hydrator import hydrate_by_name, list_sections, needs_rehydration
from ctxpack.core.packer.compressor import compress
from ctxpack.core.packer.conflict import detect_conflicts
from ctxpack.core.packer.entity_resolver import resolve_entities
from ctxpack.core.serializer import serialize_section

LENGTHS = [8_000, 32_000, 64_000]
RESULTS_DIR = os.path.join("ctxpack", "benchmarks", "agentic", "results")
BM25_BUDGET_BPE = 3_500


# ---------------------------------------------------------------------------
# Compaction summary (custom call: needs a larger max_tokens than fidelity's)
# ---------------------------------------------------------------------------

def _summarize_anthropic(transcript: str, *, model: str, api_key: str) -> str:
    prompt = (
        "You are compacting an agent coding session so work can continue in a "
        "fresh context window. Summarize the session transcript below, "
        "preserving: key decisions and their rationale, FINAL configuration "
        "values, root causes found, incidents and fixes, and current state. "
        "Stay under 1500 tokens.\n\n=== TRANSCRIPT ===\n" + transcript
    )
    payload = json.dumps({
        "model": model, "max_tokens": 2000, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"]
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            if attempt == 3:
                return f"(error: {e})"
            time.sleep(4 * (2 ** attempt))
    return "(error: unreachable)"


# ---------------------------------------------------------------------------
# BM25 baseline (Okapi, self-contained)
# ---------------------------------------------------------------------------

_TOK_RE = re.compile(r"[a-zA-Z0-9_]+")


def _bm25_select(episodes: list[str], query: str, budget_bpe: int) -> str:
    k1, b = 1.5, 0.75
    docs = [[t.lower() for t in _TOK_RE.findall(e)] for e in episodes]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / max(1, n)
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q_terms = [t.lower() for t in _TOK_RE.findall(query)]
    scores = []
    for i, d in enumerate(docs):
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in q_terms:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        scores.append((s, i))
    scores.sort(key=lambda x: (-x[0], x[1]))
    picked, used = [], 0
    for s, i in scores:
        if s <= 0 and picked:
            break
        cost = count_bpe_tokens(episodes[i], model="claude")
        if used + cost > budget_bpe and picked:
            break
        picked.append(i)
        used += cost
        if len(picked) >= 16:
            break
    picked.sort()  # restore chronological order
    return "\n\n".join(episodes[i] for i in picked)


# ---------------------------------------------------------------------------
# CTX condition: steps -> packed doc -> route -> hydrate
# ---------------------------------------------------------------------------

def _build_ctx_doc(steps: list[dict]):
    corpus = parse_steps(steps, domain="meridian-session")
    resolve_entities(corpus)
    conflicts = detect_conflicts(corpus)
    corpus.warnings.extend(conflicts)
    return compress(corpus), len(conflicts)


def _build_index(doc) -> str:
    """L3-style directory index: section names only (tool noise collapsed)."""
    names = [s["name"] for s in list_sections(doc)]
    semantic = [n for n in names if not n.startswith("ENTITY-TOOL-")]
    tools = [n for n in names if n.startswith("ENTITY-TOOL-")]
    lines = ["Agent session memory. Sections available for hydration:"]
    lines += [f"  {n}" for n in semantic]
    if tools:
        lines.append(f"  (+{len(tools)} tool-call records: "
                     + ", ".join(tools[:8]) + (" ..." if len(tools) > 8 else ""))
    lines.append("Config entities record every revision in chronological order; "
                 "the LAST value listed is the current one.")
    return "\n".join(lines)


def _route(index_text: str, question: str, doc, *, model, api_key, provider,
           max_sections: int = 6) -> list[str]:
    names = [s["name"] for s in list_sections(doc)]
    prompt = (
        f"Question: \"{question}\"\n\n"
        f"Which 1-{max_sections} sections should be retrieved to answer it? "
        f"Respond with ONLY a JSON array of section names. "
        f"If nothing is relevant, respond [\"NONE\"]."
    )
    resp = _ask_llm(prompt, index_text, model=model, api_key=api_key, provider=provider)
    clean = resp.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    valid = set(names)
    try:
        requested = [s for s in json.loads(clean) if s in valid]
    except (json.JSONDecodeError, ValueError):
        requested = [s for s in re.findall(r'"([\w-]+)"', resp) if s in valid]
    return requested


def _ctx_answer(doc, index_text: str, question: str, *, model, api_key, provider):
    t_route = count_bpe_tokens(index_text, model=model)
    requested = _route(index_text, question, doc, model=model,
                       api_key=api_key, provider=provider)
    if not requested:
        # Nothing routed: answer from the index alone (adversarial questions)
        time.sleep(_INTER_CALL_DELAY)
        answer = _ask_llm(question, index_text, model=model,
                          api_key=api_key, provider=provider)
        return answer, t_route, requested, False

    hyd = hydrate_by_name(doc, requested, include_header=True)
    parts = [hyd.header_text] if hyd.header_text else []
    for sec in hyd.sections:
        parts.extend(serialize_section(sec, natural_language=True))
    hydrated_text = index_text + "\n\n=== HYDRATED SECTIONS ===\n" + "\n".join(parts)

    time.sleep(_INTER_CALL_DELAY)
    answer = _ask_llm(question, hydrated_text, model=model,
                      api_key=api_key, provider=provider)

    rehydrated = False
    if needs_rehydration(answer):
        time.sleep(_INTER_CALL_DELAY)
        more = _route(index_text, question + " (previous sections were insufficient; "
                      "pick DIFFERENT additional sections)", doc,
                      model=model, api_key=api_key, provider=provider, max_sections=4)
        new = [s for s in more if s.upper() not in {r.upper() for r in requested}]
        if new:
            rehydrated = True
            extra = hydrate_by_name(doc, new, include_header=False)
            for sec in extra.sections:
                hydrated_text += "\n" + "\n".join(
                    serialize_section(sec, natural_language=True))
            requested += new
            time.sleep(_INTER_CALL_DELAY)
            answer = _ask_llm(question, hydrated_text, model=model,
                              api_key=api_key, provider=provider)

    total_bpe = t_route + count_bpe_tokens(hydrated_text, model=model)
    return answer, total_bpe, requested, rehydrated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    smoke = "--smoke" in sys.argv
    lengths = [8_000] if smoke else LENGTHS

    provider, api_key, model = _detect_provider()
    if not api_key:
        print("No API key found - aborting.")
        sys.exit(1)
    j_model, j_key, j_provider = _resolve_judge_params(
        None, None, None, model, api_key, provider)
    print(f"Answerer: {model} ({provider})  Judge: {j_model} ({j_provider})")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    all_results = {"model": model, "judge": j_model, "lengths": {}}

    for target in lengths:
        bundle = generate_trajectory(target)
        questions = bundle.questions[:3] if smoke else bundle.questions
        print(f"\n=== Trajectory {target} BPE (actual {bundle.actual_bpe}, "
              f"{len(bundle.episodes)} episodes, {len(bundle.steps)} steps) ===")

        # Build per-condition contexts
        doc, n_conflicts = _build_ctx_doc(bundle.steps)
        index_text = _build_index(doc)
        index_bpe = count_bpe_tokens(index_text, model=model)
        n_sections = len(list_sections(doc))
        print(f"CTX doc: {n_sections} sections, index {index_bpe} BPE, "
              f"{n_conflicts} conflicts detected")

        print("Generating compaction summary...")
        summary = _summarize_anthropic(bundle.transcript, model=model, api_key=api_key)
        summary_bpe = count_bpe_tokens(summary, model=model)
        print(f"Summary: {summary_bpe} BPE")

        conditions = ["RAW", "COMPACT", "BM25", "CTX"]
        rows = []
        for qi, q in enumerate(questions):
            for cond in conditions:
                time.sleep(_INTER_CALL_DELAY)
                meta = {}
                if cond == "RAW":
                    ctx_text = bundle.transcript
                    answer = _ask_llm(q["question"], ctx_text, model=model,
                                      api_key=api_key, provider=provider)
                    bpe = bundle.actual_bpe
                elif cond == "COMPACT":
                    answer = _ask_llm(q["question"], summary, model=model,
                                      api_key=api_key, provider=provider)
                    bpe = summary_bpe
                elif cond == "BM25":
                    sel = _bm25_select(bundle.episodes, q["question"], BM25_BUDGET_BPE)
                    answer = _ask_llm(q["question"], sel, model=model,
                                      api_key=api_key, provider=provider)
                    bpe = count_bpe_tokens(sel, model=model)
                else:  # CTX
                    answer, bpe, requested, rehyd = _ctx_answer(
                        doc, index_text, q["question"],
                        model=model, api_key=api_key, provider=provider)
                    meta = {"sections": requested, "rehydrated": rehyd}

                rule = _grade_answer(answer, q["expected"])
                time.sleep(_INTER_CALL_DELAY)
                judge_resp, judge_err = _llm_judge(
                    q["question"], q["expected"], answer,
                    model=j_model, api_key=j_key, provider=j_provider)
                judge = (not judge_err and "CORRECT" in judge_resp.upper()
                         and "INCORRECT" not in judge_resp.upper())

                rows.append({"id": q["id"], "type": q["type"], "cond": cond,
                             "bpe": bpe, "rule": rule, "judge": judge,
                             "judge_err": judge_err, "answer": answer[:400], **meta})
                print(f"  [{qi + 1:2}/{len(questions)}] {q['id']:3} {cond:8} "
                      f"{bpe:>7} BPE  judge={'Y' if judge else 'N'}"
                      f"{' (jerr)' if judge_err else ''}")

        # Aggregate per condition
        agg = {}
        for cond in conditions:
            sub = [r for r in rows if r["cond"] == cond]
            agg[cond] = {
                "judge_pct": round(100 * sum(r["judge"] for r in sub) / len(sub), 1),
                "rule_pct": round(100 * sum(r["rule"] for r in sub) / len(sub), 1),
                "avg_bpe": round(sum(r["bpe"] for r in sub) / len(sub)),
                "by_type": {
                    t: round(100 * sum(r["judge"] for r in sub if r["type"] == t)
                             / max(1, sum(1 for r in sub if r["type"] == t)), 1)
                    for t in ["static", "updated", "aggregate", "absent"]
                },
            }
        all_results["lengths"][str(target)] = {
            "actual_bpe": bundle.actual_bpe, "sections": n_sections,
            "index_bpe": index_bpe, "summary_bpe": summary_bpe,
            "conflicts": n_conflicts, "aggregate": agg, "rows": rows,
        }

        print(f"\n  {'condition':10} {'judge':>6} {'rule':>6} {'avg BPE':>9}")
        for cond in conditions:
            a = agg[cond]
            print(f"  {cond:10} {a['judge_pct']:>5}% {a['rule_pct']:>5}% "
                  f"{a['avg_bpe']:>9}")

    out = os.path.join(RESULTS_DIR,
                       f"agentic_niah-{model}{'-smoke' if smoke else ''}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
