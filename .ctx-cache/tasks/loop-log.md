# Code Packer Loop Log

One line per shipped task. Append-only.

| Date | Task | Mode | Tests added | Regression | Notes |
|---|---|---|---|---|---|
| 2026-05-12 | CP-001 — Scaffold + fixture repo + slow marker contract | Option C (manual) | 10 in `tests/code/test_scaffold.py` | 867 passed / 0 failed / 57 deselected (slow) | Established `.ctx-cache/tasks/` convention. Slow-marker contract now load-bearing for discipline step [7]. |
| 2026-05-12 | CP-002 — Tree-sitter Python parser wrapper | Option C (manual) | 25 in `tests/code/test_parser_python.py` | 892 passed / 0 failed / 57 deselected (slow) | Optional `code` extra in pyproject.toml. Acceptance deviation noted: returns ParseResult wrapping Tree, not bare Tree. Parser singleton with lazy init + lock. |
