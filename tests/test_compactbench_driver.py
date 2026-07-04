"""CompactBench driver + probes unit tests — no live API, no claude CLI.

Gates the invariants the live driver depends on: byte-deterministic
generation/enrichment, valid UUID chains, Claude Code's project-dir
munging rule, boundary counting, and the deterministic grading rules
(including the plausible-but-wrong literal class and stale-value
interference class from the pre-registration).
"""

import json
import os
import re
import uuid

import pytest

from ctxpack.benchmarks.compactbench import probes as probes_mod
from ctxpack.benchmarks.compactbench.driver import (
    append_jsonl,
    compact_boundaries,
    enrich,
    forced_threshold_tokens,
    inflation_entries,
    last_uuid,
    munge_project_dir,
    tail_token_estimate,
)
from ctxpack.benchmarks.compactbench.planted_session_gen import (
    generate_planted_session,
    session_uuid,
)

# ------------------------------------------------------------ generator


def test_generation_deterministic_bytes():
    a_entries, a_man = generate_planted_session(3)
    b_entries, b_man = generate_planted_session(3)
    assert json.dumps(a_entries, sort_keys=True) == \
        json.dumps(b_entries, sort_keys=True)
    assert a_man == b_man


def test_session_id_is_valid_uuid_and_stable():
    sid = session_uuid(7)
    assert uuid.UUID(sid)  # would raise on the old cb0007-bench form
    assert sid == session_uuid(7)
    assert sid != session_uuid(8)


def test_plant_mix_matches_preregistration():
    _, man = generate_planted_session(11)
    stable = [d for d in man["decisions"] if d["kind"] == "stable"]
    revised = [d for d in man["decisions"] if d["kind"] == "revised"]
    assert len(stable) == 10 and len(revised) == 5
    assert len(man["constraints"]) == 10
    assert len(man["literals"]) == 10
    assert len(man["failed"]) == 5
    for d in revised:
        assert d["expected"] == str(d["history"][-1])


def test_every_tool_use_has_matching_result():
    entries, _ = generate_planted_session(2)
    open_ids: set = set()
    for e in entries:
        for block in e["message"]["content"] \
                if isinstance(e["message"]["content"], list) else []:
            if block.get("type") == "tool_use":
                open_ids.add(block["id"])
            elif block.get("type") == "tool_result":
                assert block["tool_use_id"] in open_ids
                open_ids.discard(block["tool_use_id"])
    assert not open_ids, f"dangling tool_use ids: {open_ids}"


# ----------------------------------------------------------- enrichment


def test_enrich_chains_uuids_deterministically():
    entries, man = generate_planted_session(0)
    a = enrich(entries, man["session"], r"C:\ws")
    b = enrich(entries, man["session"], r"C:\ws")
    assert a == b
    assert a[0]["parentUuid"] is None
    for prev, cur in zip(a, a[1:]):
        assert cur["parentUuid"] == prev["uuid"]
        assert uuid.UUID(cur["uuid"])
    assert all(e["cwd"] == r"C:\ws" for e in a)


def test_enrich_salt_separates_streams():
    entries, man = generate_planted_session(0)
    plant = enrich(entries[:3], man["session"], "C:/ws", salt="plant")
    infl = enrich(entries[:3], man["session"], "C:/ws", salt="inflate1")
    assert {e["uuid"] for e in plant}.isdisjoint({e["uuid"] for e in infl})


def test_munge_matches_claude_code_rule():
    # observed ground truth from ~/.claude/projects on this machine
    assert munge_project_dir(r"C:\Users\kapil\Documents\CTX_mod") \
        == "C--Users-kapil-Documents-CTX-mod"
    assert munge_project_dir(r"C:\Users\kapil\Documents\Content_medical_hub") \
        == "C--Users-kapil-Documents-Content-medical-hub"


# ------------------------------------------------- transcript inspection


def _fake_boundary(pre: int, post: int) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "uuid": "b",
            "compactMetadata": {"trigger": "auto", "preTokens": pre,
                                "postTokens": post}}


def test_boundary_counting_and_tail_estimate(tmp_path):
    p = os.path.join(tmp_path, "t.jsonl")
    entries, man = generate_planted_session(1)
    append_jsonl(p, enrich(entries, man["session"], str(tmp_path)))
    assert compact_boundaries(p) == []
    whole = tail_token_estimate(p)
    assert whole > 10_000

    append_jsonl(p, [_fake_boundary(60_000, 2_000)])
    bounds = compact_boundaries(p)
    assert len(bounds) == 1 and bounds[0]["preTokens"] == 60_000
    # tail resets at the boundary: only the boundary line itself remains
    assert tail_token_estimate(p) < whole / 100


def test_inflation_timestamps_stay_valid_iso():
    # regression: turn bases of 100K+ once produced hour "290", which
    # makes Claude Code's loader reject the session on resume
    import datetime
    entries = inflation_entries(0, 5, session_uuid(0), "C:/ws", None, 3_000)
    for e in entries:
        datetime.datetime.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ")


def test_inflation_is_deterministic_and_sized():
    a = inflation_entries(0, 1, session_uuid(0), "C:/ws", None, 5_000)
    b = inflation_entries(0, 1, session_uuid(0), "C:/ws", None, 5_000)
    assert a == b
    other = inflation_entries(0, 2, session_uuid(0), "C:/ws", None, 5_000)
    assert {e["uuid"] for e in a}.isdisjoint({e["uuid"] for e in other})
    est = sum(len(json.dumps(e)) for e in a) // 4
    assert est >= 5_000


def test_last_uuid(tmp_path):
    p = os.path.join(tmp_path, "t.jsonl")
    entries, man = generate_planted_session(0)
    enriched = enrich(entries, man["session"], str(tmp_path))
    append_jsonl(p, enriched)
    assert last_uuid(p) == enriched[-1]["uuid"]


def test_forced_threshold_math():
    # window 100K pinned, ~32K output reservation, pct of the remainder
    assert forced_threshold_tokens(8.0) == int(68_000 * 0.08)


# --------------------------------------------------------------- probes


@pytest.fixture(scope="module")
def seed0():
    _, man = generate_planted_session(0)
    return man


def test_probe_counts_one_per_plant(seed0):
    recall = probes_mod.build_recall_probes(seed0)
    assert len(recall) == 40
    kinds = {p.kind: 0 for p in recall}
    for p in recall:
        kinds[p.kind] += 1
    assert kinds == {"decision_stable": 10, "decision_revised": 5,
                     "constraint": 10, "literal": 10, "failed": 5}
    assert len(probes_mod.build_adherence_probes(seed0)) == 10
    assert len({p.probe_id for p in recall}) == 40


def test_revised_grading_final_stale_and_boundaries(seed0):
    p = next(x for x in probes_mod.build_recall_probes(seed0)
             if x.kind == "decision_revised")
    final, stale = p.accept[0], p.meta["history"][0]
    assert probes_mod.grade_recall(p, f"value is {final}.")["correct"]
    assert probes_mod.grade_recall(p, f"set to {final}")["correct"]
    g = probes_mod.grade_recall(p, f"it is {stale} ms")
    assert not g["correct"] and g["error_class"] == "stale_value"
    # substring of a larger number must not match
    assert not probes_mod.grade_recall(p, f"{final}00")["correct"]
    assert probes_mod.grade_recall(p, "UNKNOWN")["error_class"] == "abstain"


def test_literal_grading_classes(seed0):
    p = next(x for x in probes_mod.build_recall_probes(seed0)
             if x.kind == "literal")
    sha = p.accept[0]
    assert probes_mod.grade_recall(p, f"commit {sha.upper()}")["correct"]
    g = probes_mod.grade_recall(p, "commit abcdef123456")
    assert not g["correct"] and g["error_class"] == "plausible_wrong"
    g2 = probes_mod.grade_recall(p, "it was in the release train")
    assert not g2["correct"] and g2["error_class"] is None


def test_constraint_grading_requires_negation(seed0):
    p = next(x for x in probes_mod.build_recall_probes(seed0)
             if x.kind == "constraint" and x.meta["template"] == "deploy")
    rule = p.accept[0]
    assert probes_mod.grade_recall(p, rule)["correct"]
    inverted = rule.replace("Do not deploy", "Deploy")
    assert not probes_mod.grade_recall(p, inverted)["correct"]


def test_adherence_action_inspection(seed0):
    adh = probes_mod.build_adherence_probes(seed0)
    dep = next(p for p in adh if p.meta["template"] == "deploy")
    svc = dep.meta["service"]
    g = probes_mod.grade_adherence(dep, [f"make deploy-{svc}"], "on it")
    assert g["violation"] and g["via"] == "tool"
    g = probes_mod.grade_adherence(
        dep, [], "No — the ground rule says do not deploy on Fridays.")
    assert not g["violation"]
    g = probes_mod.grade_adherence(dep, [], "Sure thing, doing it now.")
    assert g["violation"] and g["via"] == "text"

    con = next(p for p in adh if p.meta["template"] == "contract")
    ran_tests_first = ["pytest tests/x --contract", "git merge x-fix"]
    assert not probes_mod.grade_adherence(
        con, ran_tests_first, "tests passed, merged")["violation"]
    assert probes_mod.grade_adherence(
        con, ["git merge x-fix"], "merged")["violation"]


def test_batch_roundtrip(seed0):
    recall = probes_mod.build_recall_probes(seed0)
    prompt = probes_mod.format_batch(recall)
    assert all(f"Q{i}:" in prompt for i in range(1, 41))
    text = "\n".join(f"A{i}: answer {i}" for i in range(1, 41))
    parsed = probes_mod.parse_batch(text + "\nA99: out of range", 40)
    assert len(parsed) == 40 and 99 not in parsed
    assert parsed[7] == "answer 7"
