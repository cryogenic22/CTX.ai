"""Deterministic service-dependency graph corpus for graph-walk queries.

Adapted from OpenAI's GraphWalks: a dependency graph is embedded in long
prose (a service catalog); the model must answer topology questions
(forward deps, reverse deps / "parents", BFS within 2 hops).

Gold answers are computed from the generator's edge list, so scoring is
exact set-F1 — no LLM judge needed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

_ADJ = ["amber", "basalt", "cobalt", "delta", "ember", "flint", "granite",
        "harbor", "indigo", "juniper", "krypton", "lumen", "mesa", "nimbus",
        "onyx", "pumice", "quartz", "russet", "sable", "topaz", "umber",
        "vertex", "willow", "xenon", "yarrow", "zephyr"]
_NOUN = ["auth", "billing", "cache", "dispatch", "events", "fx", "gateway",
         "hooks", "identity", "journal", "kyc", "ledger", "metrics",
         "notify", "orders", "payouts", "quotes", "risk", "search", "tax",
         "upload", "vault", "wallet", "export", "yield", "zones"]

_TEAMS = ["platform", "payments", "risk", "identity", "data", "growth"]
_TIERS = ["tier-0", "tier-1", "tier-2"]


def _svc_name(i: int) -> str:
    return f"SVC-{_ADJ[i % 26].upper()}-{_NOUN[(i // 26 + i) % 26].upper()}"


@dataclass
class GraphBundle:
    nodes: list[str] = field(default_factory=list)
    deps: dict[str, list[str]] = field(default_factory=dict)     # directed: X depends on [...]
    catalog_text: str = ""                                       # RAW condition
    steps: list[dict] = field(default_factory=list)              # CTX packing input
    questions: list[dict] = field(default_factory=list)          # with gold sets


def _filler_prose(rng: random.Random, name: str, others: list[str]) -> str:
    """Runbook-style noise mentioning other services WITHOUT edge semantics."""
    distract = rng.sample(others, k=min(4, len(others)))
    return (
        f"Runbook: during the 2026-0{rng.randint(1, 6)} incident review, "
        f"{distract[0].lower()} was initially suspected but cleared after "
        f"trace analysis. On-call should check saturation dashboards before "
        f"paging. Deploys freeze on Fridays. A migration to the v2 SDK is "
        f"planned for Q{rng.randint(3, 4)}; {distract[1].lower()} completed "
        f"the same migration earlier this year. SLO reviews run monthly and "
        f"error budgets reset on the 1st. Load tests run at 2x peak each "
        f"quarter; last run sustained {rng.randint(2, 40)}k rps with p99 "
        f"under {rng.randint(80, 900)}ms. "
        f"Incident history: {rng.randint(0, 4)} SEV-2s in the trailing year; "
        f"the postmortem for INC-{rng.randint(1000, 9999)} noted that alert "
        f"routing initially paged the {rng.choice(_TEAMS)} team by mistake. "
        f"Capacity: {rng.randint(2, 24)} pods per zone across "
        f"{rng.randint(2, 4)} zones, HPA target {rng.randint(50, 80)}% CPU. "
        f"Config: request timeout {rng.randint(200, 2000)}ms, circuit breaker "
        f"trips at {rng.randint(20, 60)}% error rate over {rng.randint(10, 60)}s, "
        f"retry budget {rng.randint(1, 3)} attempts with jitter. Shares a "
        f"failure domain review with {distract[2].lower()} (no runtime link). "
        f"Dashboards: golden-signals board {rng.randint(100, 999)}; traces "
        f"sampled at {rng.choice(['1', '5', '10'])}%. Note: {distract[3].lower()} "
        f"appears in the same cost-allocation group only."
    )


def generate_service_graph(n_nodes: int, seed: int = 7) -> GraphBundle:
    rng = random.Random(seed)
    nodes = [_svc_name(i) for i in range(n_nodes)]

    # Directed DAG-ish: node i depends on 1-3 earlier nodes
    deps: dict[str, list[str]] = {nodes[0]: []}
    for i in range(1, n_nodes):
        k = rng.choice([1, 1, 2, 2, 3])
        deps[nodes[i]] = sorted(rng.sample(nodes[:i], k=min(k, i)))

    blocks = []
    steps = []
    for i, name in enumerate(nodes):
        team = rng.choice(_TEAMS)
        tier = rng.choice(_TIERS)
        port = rng.randint(7000, 9999)
        sla = rng.choice(["99.9", "99.95", "99.99"])
        dep_line = (", ".join(deps[name]) if deps[name] else "none")
        prose = _filler_prose(rng, name, [n for n in nodes if n != name])
        blocks.append(
            f"## {name}\n"
            f"Owner: {team}. Criticality: {tier}. Port: {port}. SLA: {sla}%.\n"
            f"Declared dependencies: {dep_line}.\n"
            f"{prose}"
        )
        steps.append({"entities": [{
            "name": name,
            "owner": team, "tier": tier, "port": str(port), "sla": sla,
            "depends_on": (", ".join(f"@ENTITY-{d}" for d in deps[name])
                           if deps[name] else "none"),
            "notes": prose,
        }]})

    catalog_text = ("# Meridian service catalog\n\n" + "\n\n".join(blocks))

    # Reverse index for parents questions
    rdeps: dict[str, list[str]] = {n: [] for n in nodes}
    for src, targets in deps.items():
        for t in targets:
            rdeps[t].append(src)

    # Undirected adjacency for BFS questions
    adj: dict[str, set] = {n: set() for n in nodes}
    for src, targets in deps.items():
        for t in targets:
            adj[src].add(t)
            adj[t].add(src)

    def bfs2(start: str) -> set:
        frontier = set(adj[start])
        for m in list(frontier):
            frontier |= adj[m]
        frontier.discard(start)
        return frontier

    # Pick question subjects with interesting neighborhoods (degree >= 2)
    ranked = sorted(nodes, key=lambda n: -(len(deps[n]) + len(rdeps[n])))
    subjects = [n for n in ranked if len(deps[n]) >= 1 and len(rdeps[n]) >= 1]
    rng.shuffle(subjects)

    questions = []
    for qi, kind in enumerate(["forward"] * 4 + ["reverse"] * 4 + ["bfs2"] * 4):
        subj = subjects[qi % len(subjects)]
        if kind == "forward":
            gold = set(deps[subj])
            qtext = (f"According to the declared dependencies, which services "
                     f"does {subj} directly depend on?")
        elif kind == "reverse":
            gold = set(rdeps[subj])
            qtext = (f"According to the declared dependencies, which services "
                     f"directly depend on {subj}?")
        else:
            gold = bfs2(subj)
            qtext = (f"Treating declared dependencies as undirected links, "
                     f"list ALL services within 2 hops of {subj}.")
        questions.append({
            "id": f"G{qi + 1:02d}", "kind": kind, "subject": subj,
            "question": qtext + " Respond with ONLY a JSON array of service names.",
            "gold": sorted(gold),
        })

    return GraphBundle(nodes=nodes, deps=deps, catalog_text=catalog_text,
                       steps=steps, questions=questions)
