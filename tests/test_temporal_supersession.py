"""Temporal supersession — a changed value is a state update, not a pile-up.

Guards the 2026-07-03 audit's defect #2: revised config values accumulated
as duplicate keys with conflicts=0 (the proactive-interference failure mode
from Wang & Sun 2025).
"""

import datetime
import time

from ctxpack.agent.session import AgentSession
from ctxpack.agent.state_parser import parse_steps
from ctxpack.core.hydrator import hydrate_by_name
from ctxpack.core.layers import ContextLayer
from ctxpack.core.model import KeyValue, Provenance, Section
from ctxpack.core.packer.entity_resolver import resolve_entities
from ctxpack.core.packer.ir import IRSource


def _session_with_revisions(supersede: bool = True) -> AgentSession:
    session = AgentSession(domain="t", token_budget=100_000, supersede=supersede)
    session.update({"entities": [{"name": "CFG", "backoff_ms": "250"}]})
    session.update({"entities": [{"name": "CFG", "backoff_ms": "500"}]})
    session.update({"entities": [{"name": "CFG", "backoff_ms": "750"}]})
    return session


def _cfg_fields(session: AgentSession) -> dict[str, list[str]]:
    ent = next(e for e in session._corpus.entities if e.name == "CFG")
    out: dict[str, list[str]] = {}
    for f in ent.fields:
        out.setdefault(f.key, []).append(f.value)
    return out


def test_latest_value_wins():
    fields = _cfg_fields(_session_with_revisions())
    assert fields["BACKOFF-MS"] == ["750"], (
        f"expected single current value 750, got {fields['BACKOFF-MS']}"
    )


def test_history_chain_recorded():
    fields = _cfg_fields(_session_with_revisions())
    chain = fields["SUPERSEDED-BACKOFF-MS"]
    assert len(chain) == 1
    assert "250@step-0" in chain[0]
    assert "500@step-1" in chain[0]
    assert "750@step-2" in chain[0]


def test_history_does_not_stack_across_resolves():
    session = _session_with_revisions()
    # Two more revisions → two more resolve passes over existing history
    session.update({"entities": [{"name": "CFG", "backoff_ms": "900"}]})
    session.update({"entities": [{"name": "CFG", "backoff_ms": "1000"}]})
    fields = _cfg_fields(session)
    assert fields["BACKOFF-MS"] == ["1000"]
    chain = fields["SUPERSEDED-BACKOFF-MS"]
    assert len(chain) == 1, f"history stacked: {chain}"
    for val in ("250", "500", "750", "900", "1000"):
        assert val in chain[0], f"{val} missing from chain {chain[0]!r}"


def test_supersede_off_keeps_all_values():
    fields = _cfg_fields(_session_with_revisions(supersede=False))
    assert sorted(fields["BACKOFF-MS"]) == ["250", "500", "750"]


def test_two_constraints_both_stay_active():
    """Two different rules are two facts, not a revision — a second
    constraint must never retire the first into SUPERSEDED history."""
    session = AgentSession(domain="t", token_budget=100_000)
    session.update({"entities": [{"name": "API",
                                  "constraint": "never retry on 4xx"}]})
    session.update({"entities": [{"name": "API",
                                  "constraint": "do not log request bodies"}]})
    ent = next(e for e in session._corpus.entities if e.name == "API")
    active = sorted(f.value for f in ent.fields if f.key == "CONSTRAINT")
    assert active == ["do not log request bodies", "never retry on 4xx"]
    assert not any(f.key.startswith("SUPERSEDED-CONSTRAINT")
                   for f in ent.fields)


def test_alias_merge_absorbs_all_prior_histories():
    from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField

    def _ent(name, key, val, hist, step):
        src = IRSource(file=f"step-{step}", line_start=step)
        e = IREntity(name=name, sources=[src], salience=1.0)
        e.fields.append(IRField(key=key, value=val, raw_value=val, source=src))
        e.fields.append(IRField(key=f"SUPERSEDED-{key}", value=hist,
                                raw_value=hist, source=src))
        return e

    corpus = IRCorpus(domain="t")
    corpus.entities.append(_ent("CFG", "X", "2", "1@step-0 -> 2@step-1", 1))
    corpus.entities.append(_ent("CONFIG", "X", "9", "7@step-2 -> 9@step-3", 3))
    resolve_entities(corpus, alias_map={"CFG": ["CONFIG"]},
                     supersede_by_recency=True)
    ent = corpus.entities[0]
    chain = next(f.value for f in ent.fields if f.key == "SUPERSEDED-X")
    for elem in ("1@step-0", "2@step-1", "7@step-2", "9@step-3"):
        assert elem in chain, f"{elem} lost from merged history: {chain}"


def test_multi_value_keys_exempt():
    steps = [
        {"entities": [{"name": "SVC", "depends_on": "@ENTITY-A"}]},
        {"entities": [{"name": "SVC", "depends_on": "@ENTITY-B"}]},
    ]
    corpus = parse_steps(steps)
    resolve_entities(corpus, supersede_by_recency=True)
    ent = next(e for e in corpus.entities if e.name == "SVC")
    values = [f.value for f in ent.fields if f.key == "DEPENDS-ON"]
    assert sorted(values) == ["@ENTITY-A", "@ENTITY-B"], (
        "relationship keys must never be superseded"
    )


def test_turn_provenance_renders_and_orders():
    src = IRSource(file="session-abc", turn=141)
    assert str(src) == "session-abc#turn141"

    # turn ordering beats insertion order in supersession
    steps = [{"entities": [{"name": "CFG", "v": "new"}]},
             {"entities": [{"name": "CFG", "v": "old"}]}]
    corpus = parse_steps(steps)
    # Manually assign turns: first-listed fact is actually the LATER turn
    corpus.entities[0].fields[0].source.turn = 10
    corpus.entities[1].fields[0].source.turn = 3
    resolve_entities(corpus, supersede_by_recency=True)
    ent = corpus.entities[0]
    current = [f.value for f in ent.fields if f.key == "V"]
    assert current == ["new"], f"turn-ordered recency failed: {current}"


def test_hydrator_drops_expired_sections():
    past = time.time() - 3600
    future = time.time() + 3600
    now_iso = datetime.datetime.now().isoformat()

    def _section(name: str, expires_at) -> Section:
        return Section(name=name, children=(
            KeyValue(key="STATE", value="x"),
            Provenance(source=f"{name.lower()}.md",
                       layer=ContextLayer.AMBIENT,
                       expires_at=expires_at),
        ))

    from ctxpack.core.model import CTXDocument, Header, Layer
    doc = CTXDocument(
        header=Header(magic="§CTX", version="1.0", layer=Layer.L2,
                      status_fields=(KeyValue(key="DOMAIN", value="t"),),
                      metadata=()),
        body=(_section("STALE", past), _section("FRESH", future),
              _section("ETERNAL", None)),
    )

    kept = hydrate_by_name(
        doc, ["STALE", "FRESH", "ETERNAL"], include_header=False,
        drop_expired_as_of=now_iso,
    )
    names = [s.name for s in kept.sections]
    assert "STALE" not in names
    assert "FRESH" in names and "ETERNAL" in names

    # default: expired sections still served (back-compat)
    kept_default = hydrate_by_name(
        doc, ["STALE", "FRESH", "ETERNAL"], include_header=False,
    )
    assert len(kept_default.sections) == 3
