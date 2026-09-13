"""P0 trust repairs — determinism, transient-error handling, provenance.

Guards the 2026-07-03 audit fixes:
- byte-identical repacks when the header date is pinned (as_of / CTXPACK_AS_OF)
- HTTP 529 (Anthropic "overloaded") treated as transient, not permanent
- AgentSession provenance carries real step indices (was: always step-0)
"""

import hashlib
import os

from ctxpack.agent.session import AgentSession
from ctxpack.agent.state_parser import parse_steps
from ctxpack.benchmarks.metrics.fidelity import _TRANSIENT_CODES
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize


def _write_corpus(root) -> str:
    (root / "entities").mkdir()
    (root / "entities" / "customer.yaml").write_text(
        "entities:\n"
        "  - name: Customer\n"
        "    identifier: customer_id (UUID v4)\n"
        "    retention: 7 years\n"
        "    belongs_to: Merchant\n",
        encoding="utf-8",
    )
    (root / "entities" / "merchant.yaml").write_text(
        "entities:\n"
        "  - name: Merchant\n"
        "    identifier: merchant_id\n"
        "    commission: 15 percent\n",
        encoding="utf-8",
    )
    (root / "rules.md").write_text(
        "# RULES\n\n- Do not delete audit records\n- Retention is 7 years\n",
        encoding="utf-8",
    )
    return str(root)


def _pack_sha(corpus_dir: str, as_of: str) -> str:
    result = pack(corpus_dir, layers=["L2", "L3"], as_of=as_of)
    parts = [serialize(result.document)]
    if result.l3_document is not None:
        parts.append(serialize(result.l3_document))
    if result.manifest_document is not None:
        parts.append(serialize(result.manifest_document))
    blob = "\n===\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def test_pack_is_byte_deterministic_with_as_of(tmp_path):
    corpus = _write_corpus(tmp_path)
    sha1 = _pack_sha(corpus, as_of="2026-01-01")
    sha2 = _pack_sha(corpus, as_of="2026-01-01")
    assert sha1 == sha2, "same corpus + same as_of must serialize byte-identically"


def test_as_of_env_var_pins_header_date(tmp_path):
    corpus = _write_corpus(tmp_path)
    os.environ["CTXPACK_AS_OF"] = "2025-12-31"
    try:
        result = pack(corpus)
        assert result.document.header.get("COMPRESSED") == "2025-12-31"
    finally:
        del os.environ["CTXPACK_AS_OF"]


def test_explicit_as_of_beats_env(tmp_path):
    corpus = _write_corpus(tmp_path)
    os.environ["CTXPACK_AS_OF"] = "2025-12-31"
    try:
        result = pack(corpus, as_of="2026-06-15")
        assert result.document.header.get("COMPRESSED") == "2026-06-15"
    finally:
        del os.environ["CTXPACK_AS_OF"]


def test_529_and_timeouts_are_transient():
    # 529 = Anthropic overloaded; 408/522/524 = timeout variants. Treating
    # any as permanent silently scores answers INCORRECT (v0.4 postmortem).
    for code in (408, 429, 500, 502, 503, 504, 522, 524, 529):
        assert code in _TRANSIENT_CODES, f"HTTP {code} must be retried"


def test_parse_steps_start_index_provenance():
    steps = [{"decision": "use exponential backoff"},
             {"entities": [{"name": "CFG", "v": "1"}]}]
    corpus = parse_steps(steps, start_index=5)
    assert corpus.source_files == ["step-5", "step-6"]
    ent = corpus.entities[0]
    assert ent.sources[0].file == "step-6"


def test_agent_session_provenance_advances():
    session = AgentSession(domain="t", token_budget=100_000)
    session.update({"entities": [{"name": "ALPHA", "v": "1"}]})
    session.update({"entities": [{"name": "BETA", "v": "2"}]})
    session.update({"entities": [{"name": "GAMMA", "v": "3"}]})
    files = set()
    for ent in session._corpus.entities:
        for src in ent.sources:
            files.add(src.file)
    assert files == {"step-0", "step-1", "step-2"}, (
        f"expected distinct step provenance, got {sorted(files)}"
    )
