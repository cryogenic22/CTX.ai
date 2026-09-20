---
description: Pre-commit attestation. Run /review, then the deterministic lane and the gates, then check the commit message carries its Decision/Constraint lines.
---

Do all four, in order. If any step produces a change, make it, re-stage, and
start again.

## 1. Run `/review`

Walk every flag against the staged diff. Report the totals.

## 2. Run the deterministic lane

```
python -m pytest tests/ -q -m "not slow"
python scripts/check_claims.py
python scripts/check_capability_registry.py
python scripts/gen_codeowners.py --check
python scripts/check_pr_template.py
```

Scope the suite to the touched area first if it is quicker, but the full
non-slow lane runs before the handoff. **Paste the real output** — never claim
a result from memory.

## 3. Show the red

For every behaviour this change adds or fixes, name the test and the count it
produced **on the parent commit**:

```
git stash && python -m pytest <the new test> -q ; git stash pop
```

A test that legitimately passes on the parent must say in its docstring whether
it is a *regression pin* (freezing existing behaviour) or a *forward guard*
(bounding new behaviour).

## 4. Check the commit message

- Cites the unit or finding it implements.
- Carries the `Decision:` / `Constraint:` / `Supersedes:` lines from the
  turn-final message, per `CLAUDE.md`.
- Says what is **not** done, if the unit is one slice of a sequence.
- Contains no unsupported quality words — comprehensive, robust,
  production-ready. `scripts/check_pr_template.py` rejects these in a PR body;
  keep them out of commit messages too.

## Report

- Flags: X PASS · Y N/A · Z FIXED · W JUSTIFIED
- Lane: pass/fail per command, with output
- Red-on-parent: test path → failure count
- Commit message: ready / needs a Decision line / needs scope note
- **Independent review still owed** — the implementer never approves their own
  diff. Say who reviews next.
