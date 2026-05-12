# Code Packer Loop Log

One line per shipped task. Append-only.

| Date | Task | Mode | Tests added | Regression | Notes |
|---|---|---|---|---|---|
| 2026-05-12 | CP-001 — Scaffold + fixture repo + slow marker contract | Option C (manual) | 10 in `tests/code/test_scaffold.py` | 867 passed / 0 failed / 57 deselected (slow) | Established `.ctx-cache/tasks/` convention. Slow-marker contract now load-bearing for discipline step [7]. |
| 2026-05-12 | CP-002 — Tree-sitter Python parser wrapper | Option C (manual) | 25 in `tests/code/test_parser_python.py` | 892 passed / 0 failed / 57 deselected (slow) | Optional `code` extra in pyproject.toml. Acceptance deviation noted: returns ParseResult wrapping Tree, not bare Tree. Parser singleton with lazy init + lock. |
| 2026-05-12 | CP-002.5 — Tokeniser pin + `count_bpe` SoT | Option C (manual) | 20 in `tests/code/test_tokens.py` | 912 passed / 0 failed / 57 deselected (slow) | Pinned cl100k_base via tiktoken. ADR 0001 written. Architectural test enforces no direct tiktoken imports outside the helper. Reference counts frozen for hello/""/short sig/non-ASCII/long generic. |
| 2026-05-12 | CP-003 — Top-level symbol extractor | Option C (manual) | 28 in `tests/code/test_symbols.py` | 940 passed / 0 failed / 57 deselected (slow) | Symbol/Kind dataclasses. Walker unwraps decorated_definition. Top-level only — methods/nested defs deferred to CP-004. Byte offsets round-trip to source. |
