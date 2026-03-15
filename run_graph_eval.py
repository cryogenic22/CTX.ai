"""Test graph-enriched L3 routing on multi-hop questions."""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(__file__))

from ctxpack.benchmarks.dotenv import load_dotenv
load_dotenv()
os.environ["CTXPACK_EVAL_PROVIDER"] = "anthropic"
os.environ["CTXPACK_EVAL_MODEL"] = "claude-opus-4-6"

from ctxpack.core.packer import pack
from ctxpack.core.entity_graph import EntityGraph
from ctxpack.core.hydrator import hydrate_by_name, list_sections
from ctxpack.core.serializer import serialize_section
from ctxpack.benchmarks.metrics.fidelity import (
    _ask_llm, _detect_provider, _grade_answer, _llm_judge,
    _resolve_judge_params, _INTER_CALL_DELAY, load_questions,
)
from ctxpack.benchmarks.metrics.cost import count_bpe_tokens

CORPUS = "ctxpack/benchmarks/scaling/enterprise_corpus"
QUESTIONS = "ctxpack/benchmarks/scaling/enterprise_questions.yaml"


def main():
    provider, api_key, eval_model = _detect_provider()
    j_model, j_key, j_provider = _resolve_judge_params(
        None, None, None, eval_model, api_key, provider
    )

    questions = load_questions(QUESTIONS)
    pack_result = pack(CORPUS)
    doc = pack_result.document
    graph = EntityGraph.from_document(doc)
    sections = list_sections(doc)
    section_names = [s["name"] for s in sections]

    # Build GRAPH-ENRICHED L3 — relationship arrows visible to LLM
    entity_secs = [s for s in sections if s["name"].startswith("ENTITY-")]
    lines = [
        "You have a domain knowledge base. Use ctx/hydrate(section=NAME) to retrieve details.",
        "",
        "Entities and their relationships:",
    ]
    for s in entity_secs:
        name = s["name"]
        neighbors = sorted(graph.neighbors(name))[:6]
        if neighbors:
            lines.append(f"  {name} -> [{', '.join(neighbors)}]")
        else:
            lines.append(f"  {name}")

    other = [s for s in sections if not s["name"].startswith("ENTITY-")]
    if other:
        lines.append("Other sections:")
        for s in other:
            lines.append(f"  {s['name']}")

    lines.extend([
        "",
        "To answer questions, hydrate relevant sections.",
        "For multi-hop questions, follow the relationship arrows to find connected entities.",
        "Request up to 5 sections if needed. Say 'not found' if no section is relevant.",
    ])

    graph_l3 = "\n".join(lines)
    graph_l3_bpe = count_bpe_tokens(graph_l3, model=eval_model)

    print(f"Graph-enriched L3: {graph_l3_bpe} BPE")
    print(f"Judge: {j_model} ({j_provider})")
    print()

    # Run ALL 30 questions with graph-enriched L3
    results = []
    for i, q in enumerate(questions):
        q_id = q["id"]
        question = q["question"]
        expected = q["expected"]
        difficulty = q["difficulty"]

        time.sleep(_INTER_CALL_DELAY)
        routing_prompt = (
            f"You have a knowledge base with these sections:\n"
            f"{json.dumps(section_names)}\n\n"
            f"Question: \"{question}\"\n\n"
            f"Check the relationship arrows in your knowledge map. "
            f"Which 1-5 sections should be retrieved? "
            f"Respond with ONLY a JSON array. "
            f"If the answer isn't in the knowledge base, respond [\"NONE\"]."
        )
        route_resp = _ask_llm(routing_prompt, graph_l3,
                              model=eval_model, api_key=api_key, provider=provider)

        # Parse
        clean = route_resp.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            requested = [s for s in json.loads(clean) if s in set(section_names) or s == "NONE"]
        except (json.JSONDecodeError, ValueError):
            requested = [s for s in re.findall(r'"([\w-]+)"', route_resp) if s in set(section_names)]
        if not requested:
            requested = ["NONE"]

        # Hydrate
        if requested != ["NONE"]:
            hydration = hydrate_by_name(doc, requested, include_header=True)
            hyd_lines = []
            if hydration.header_text:
                hyd_lines.append(hydration.header_text)
            for section in hydration.sections:
                for line in serialize_section(section, natural_language=True):
                    hyd_lines.append(line)
            hydrated_text = "\n".join(hyd_lines)
        else:
            hydrated_text = graph_l3

        hydrated_bpe = count_bpe_tokens(hydrated_text, model=eval_model)
        total_bpe = graph_l3_bpe + hydrated_bpe

        # Answer
        time.sleep(_INTER_CALL_DELAY)
        answer = _ask_llm(question, hydrated_text,
                          model=eval_model, api_key=api_key, provider=provider)

        # Re-hydration if needed
        from ctxpack.core.hydrator import needs_rehydration
        rehydrated = False
        if needs_rehydration(answer) and requested != ["NONE"]:
            time.sleep(_INTER_CALL_DELAY)
            rehyd_prompt = (
                f"Your previous answer was incomplete. Question: \"{question}\"\n"
                f"You already have: {json.dumps(requested)}\n"
                f"Available: {json.dumps(section_names)}\n"
                f"Which 1-3 ADDITIONAL sections? JSON array only."
            )
            rehyd_resp = _ask_llm(rehyd_prompt, graph_l3,
                                  model=eval_model, api_key=api_key, provider=provider)
            try:
                additional = [s for s in json.loads(rehyd_resp.strip()) if s in set(section_names)]
            except:
                additional = []

            already = set(r.upper() for r in requested)
            new_secs = [s for s in additional if s.upper() not in already]
            if new_secs:
                rehydrated = True
                rehyd_result = hydrate_by_name(doc, new_secs, include_header=False)
                for section in rehyd_result.sections:
                    for line in serialize_section(section, natural_language=True):
                        hydrated_text += "\n" + line
                requested = requested + new_secs
                hydrated_bpe = count_bpe_tokens(hydrated_text, model=eval_model)
                total_bpe = graph_l3_bpe + hydrated_bpe + 2000

                time.sleep(_INTER_CALL_DELAY)
                answer = _ask_llm(question, hydrated_text,
                                  model=eval_model, api_key=api_key, provider=provider)

        # Grade
        correct_rule = _grade_answer(answer, expected)
        time.sleep(_INTER_CALL_DELAY)
        judge_resp, judge_err = _llm_judge(question, expected, answer,
                                           model=j_model, api_key=j_key, provider=j_provider)
        correct_judge = (
            not judge_err
            and "CORRECT" in judge_resp.upper()
            and "INCORRECT" not in judge_resp.upper()
        )

        status = "Y" if correct_judge else "N"
        rehyd_tag = " [RE-HYD]" if rehydrated else ""
        secs = ", ".join(requested[:3])
        if len(secs) > 40:
            secs = secs[:40] + "..."
        print(f"  [{i+1}/30] {q_id} -> {secs:<43} {total_bpe:>6} BPE judge={status}{rehyd_tag}")

        results.append({
            "id": q_id, "difficulty": difficulty,
            "sections": len(requested), "bpe": total_bpe,
            "rule": correct_rule, "judge": correct_judge,
            "rehydrated": rehydrated,
        })

    # Summary
    total = len(results)
    judge_pct = sum(1 for r in results if r["judge"]) / total * 100
    rule_pct = sum(1 for r in results if r["rule"]) / total * 100
    avg_bpe = sum(r["bpe"] for r in results) / total
    avg_secs = sum(r["sections"] for r in results) / total
    rehyd_count = sum(1 for r in results if r["rehydrated"])

    print()
    print("=" * 70)
    print("GRAPH-ENRICHED L3 RESULTS (all 30 questions)")
    print("=" * 70)
    print(f"Fidelity: {rule_pct:.0f}% rule, {judge_pct:.0f}% judge")
    print(f"Avg BPE/query: {avg_bpe:.0f}")
    print(f"Avg sections/query: {avg_secs:.1f}")
    print(f"Re-hydrations: {rehyd_count}")
    print(f"Graph L3 BPE: {graph_l3_bpe}")
    print()

    # By difficulty
    print("By difficulty (judge):")
    for diff in ["easy", "medium", "hard"]:
        d_results = [r for r in results if r["difficulty"] == diff]
        if d_results:
            d_pct = sum(1 for r in d_results if r["judge"]) / len(d_results) * 100
            print(f"  {diff:<8} {d_pct:.0f}% ({len(d_results)} Qs)")

    print()
    print("Compare to previous (standard L3, no graph):")
    print("  Standard L3: 70% rule, 87% judge, avg 3877 BPE")
    print(f"  Graph L3:    {rule_pct:.0f}% rule, {judge_pct:.0f}% judge, avg {avg_bpe:.0f} BPE")


if __name__ == "__main__":
    main()
