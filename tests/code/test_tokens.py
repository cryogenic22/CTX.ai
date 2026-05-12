"""CP-002.5 — single source of truth for BPE counting.

Every downstream code-packer task that measures or budgets tokens
(CP-010.3 catalog row cap, CP-027 hydration budget, CP-032
catalog-size measurement, CP-036 tokens/task eval) imports
`count_bpe` from this module. Pinning the reference counts here
guards against silent drift from a future tiktoken upgrade.
"""

from __future__ import annotations

import pytest


# ── API shape ──────────────────────────────────────────────────────────


class TestApi:
    def test_module_importable(self):
        from ctxpack.core.code import tokens  # noqa: F401

    def test_count_bpe_callable(self):
        from ctxpack.core.code.tokens import count_bpe
        assert callable(count_bpe)

    def test_returns_int(self):
        from ctxpack.core.code.tokens import count_bpe
        result = count_bpe("anything")
        assert isinstance(result, int)


# ── Reference counts (the heart of the test) ────────────────────────────


class TestReferenceCounts:
    """Five reference strings span the cases that matter:

    - pure ASCII single token
    - empty string
    - short Python signature with operators
    - non-ASCII identifiers (utf-8 round-trip)
    - long generic-heavy signature (catalog soft-cap case from CP-010.3)

    Counts computed once against cl100k_base and frozen. A future
    tiktoken upgrade that shifts counts will fail here loudly.
    """

    def test_hello(self):
        from ctxpack.core.code.tokens import count_bpe
        assert count_bpe("hello") == 1

    def test_empty_string(self):
        from ctxpack.core.code.tokens import count_bpe
        assert count_bpe("") == 0

    def test_short_python_signature(self):
        from ctxpack.core.code.tokens import count_bpe
        assert count_bpe("def foo(x: int) -> str: return str(x)") == 13

    def test_non_ascii_identifiers(self):
        from ctxpack.core.code.tokens import count_bpe
        s = "def Δ_change(α: int, β: int) -> int: return β - α"
        assert count_bpe(s) == 19

    def test_long_generic_signature(self):
        """The catalog soft-cap case: deeply nested generics. CP-010.3
        truncates these mid-generic; this test pins the unTRUNCATED
        count so the truncator can be evaluated against a known
        baseline.
        """
        from ctxpack.core.code.tokens import count_bpe
        sig = (
            "def merge_caches("
            "left: dict[str, list[Optional[Foo[Bar, Baz[Qux]]]]], "
            "right: dict[str, list[Optional[Foo[Bar, Baz[Qux]]]]]"
            ") -> dict[str, list[Foo[Bar, Baz[Qux]]]]:"
        )
        assert count_bpe(sig) == 61


# ── Encoding name pinning ──────────────────────────────────────────────


class TestPinnedEncoding:
    def test_default_encoding_is_cl100k_base(self):
        """The pinned encoding must be cl100k_base. If someone flips
        the default to o200k or a Claude proxy, all downstream
        BPE counts shift and §8.6 determinism breaks across versions.
        """
        from ctxpack.core.code import tokens
        assert tokens._ENCODER_NAME == "cl100k_base"


# ── Determinism ─────────────────────────────────────────────────────────


class TestDeterminism:
    def test_repeated_calls_match(self):
        from ctxpack.core.code.tokens import count_bpe
        s = "for i in range(10): pass"
        first = count_bpe(s)
        for _ in range(5):
            assert count_bpe(s) == first

    def test_no_state_leak_between_strings(self):
        from ctxpack.core.code.tokens import count_bpe
        a = count_bpe("alpha")
        b = count_bpe("beta")
        a_again = count_bpe("alpha")
        assert a == a_again, "encoder state must not depend on prior calls"


# ── Override hook ──────────────────────────────────────────────────────


class TestOverride:
    def test_explicit_cl100k_matches_default(self):
        from ctxpack.core.code.tokens import count_bpe
        s = "x = lambda y: y * 2"
        assert count_bpe(s) == count_bpe(s, encoding="cl100k_base")

    def test_o200k_is_a_different_path(self):
        """o200k_base is available but NOT the pinned default. Passing
        it must work; result may differ from cl100k counts on some
        inputs (and may match on others — both are fine; the contract
        is "the kwarg is honoured")."""
        from ctxpack.core.code.tokens import count_bpe
        result = count_bpe("hello world", encoding="o200k_base")
        assert isinstance(result, int)
        assert result >= 1


# ── Type contract / red-team ────────────────────────────────────────────


class TestTypeContract:
    def test_bytes_input_raises_typeerror(self):
        from ctxpack.core.code.tokens import count_bpe
        with pytest.raises(TypeError):
            count_bpe(b"bytes-not-str")  # type: ignore[arg-type]

    def test_none_input_raises_typeerror(self):
        from ctxpack.core.code.tokens import count_bpe
        with pytest.raises(TypeError):
            count_bpe(None)  # type: ignore[arg-type]

    def test_int_input_raises_typeerror(self):
        from ctxpack.core.code.tokens import count_bpe
        with pytest.raises(TypeError):
            count_bpe(42)  # type: ignore[arg-type]


# ── ADR exists and names the choice ─────────────────────────────────────


class TestAdr:
    def test_adr_file_exists_and_documents_choice(self):
        """The backlog acceptance is 'documented + justified in ADR'.
        Cheapest enforcement is to assert the file exists and names
        the chosen encoding."""
        from pathlib import Path
        adr = Path(__file__).parent.parent.parent / "docs" / "adr" / "0001-tokeniser-choice.md"
        assert adr.exists(), f"ADR missing at {adr}"
        text = adr.read_text(encoding="utf-8")
        assert "cl100k_base" in text
        assert "tiktoken" in text.lower()


# ── Red-team additions ─────────────────────────────────────────────────


class TestRedTeam:
    def test_invalid_encoding_raises(self):
        """A typo in the override (e.g. 'cl101k_base') must fail
        loudly, not silently fall back to the default. Otherwise a
        researcher's A/B is meaningless and they don't know it.
        """
        from ctxpack.core.code.tokens import count_bpe
        with pytest.raises(Exception):  # tiktoken raises ValueError or its own type
            count_bpe("hi", encoding="cl101k_definitely_not_real")

    def test_whitespace_only_string(self):
        """Whitespace strings shouldn't be 0 (they're not empty) and
        shouldn't crash. cl100k treats spaces as their own tokens.
        """
        from ctxpack.core.code.tokens import count_bpe
        assert count_bpe("   ") >= 1
        assert count_bpe("\n\n\n") >= 1
        assert count_bpe("\t") >= 1

    def test_no_direct_tiktoken_import_outside_tokens_module(self):
        """ADR-pinned: bypassing count_bpe by importing tiktoken
        directly elsewhere in ctxpack/core/code/ is a measurement-drift
        risk. Enforce as a test.

        Allowlist:
        - ctxpack/core/code/tokens.py (the helper itself)
        - ctxpack/benchmarks/metrics/cost.py (sibling, different
          contract — model-specific cost estimation, not budgeting).
        - ctxpack/benchmarks/tokenizer_mapping.py (cross-encoding
          comparison tool, by design).
        """
        from pathlib import Path
        repo = Path(__file__).parent.parent.parent
        code_dir = repo / "ctxpack" / "core" / "code"
        offenders: list[str] = []
        for py_file in code_dir.rglob("*.py"):
            if py_file.name == "tokens.py":
                continue
            text = py_file.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import tiktoken") or stripped.startswith(
                    "from tiktoken"
                ):
                    offenders.append(f"{py_file.relative_to(repo)}: {stripped}")
        assert not offenders, (
            "Direct tiktoken imports outside tokens.py violate the "
            "ADR-0001 single-source-of-truth pin:\n  "
            + "\n  ".join(offenders)
        )
